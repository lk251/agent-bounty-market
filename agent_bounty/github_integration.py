from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .domain import BountyState
from .stripe_sandbox import request_digest, safe_error_message
from .util import parse_json, sha256_bytes, sha256_text, stable_json, utc_now


GITHUB_INTEGRATION_ENV = "AGENT_BOUNTY_GITHUB_INTEGRATION"
GITHUB_TOKEN_ENV = "AGENT_BOUNTY_GITHUB_TOKEN"
GITHUB_REPOSITORY_ENV = "AGENT_BOUNTY_GITHUB_REPOSITORY"
GITHUB_WEBHOOK_SECRET_ENV = "AGENT_BOUNTY_GITHUB_WEBHOOK_SECRET"
GITHUB_EXPECTED_INSTALLATION_ENV = "AGENT_BOUNTY_GITHUB_INSTALLATION_ID"
GITHUB_TRANSPORT_ENV = "AGENT_BOUNTY_GITHUB_TRANSPORT"

CONTRACT_SCHEMA = "agent-bounty-contract-v1"
CLAIM_SCHEMA = "agent-bounty-claim-v1"
SUBMISSION_SCHEMA = "agent-bounty-submission-v1"
RESULT_SCHEMA = "agent-bounty-result-v1"

CONTRACT_RE = re.compile(r"<!--\s*agent-bounty-contract-v1\s*(\{.*?\})\s*-->", re.DOTALL)
CLAIM_RE = re.compile(r"<!--\s*agent-bounty-claim-v1\s*(\{.*?\})\s*-->", re.DOTALL)
SUBMISSION_RE = re.compile(r"<!--\s*agent-bounty-submission-v1\s*(\{.*?\})\s*-->", re.DOTALL)

ALLOWED_GITHUB_EVENTS = {
    "issues",
    "issue_comment",
    "pull_request",
    "check_run",
    "check_suite",
    "workflow_run",
    "status",
    "installation",
    "repository",
}


class GitHubIntegrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitHubConfig:
    enabled: bool
    token: str | None
    repository: str | None
    webhook_secret: str | None
    expected_installation_id: str | None
    transport: str
    api_base_url: str = "https://api.github.com"

    @classmethod
    def from_env(cls) -> GitHubConfig:
        return cls(
            enabled=os.environ.get(GITHUB_INTEGRATION_ENV) == "1",
            token=os.environ.get(GITHUB_TOKEN_ENV) or os.environ.get("GH_TOKEN") or None,
            repository=os.environ.get(GITHUB_REPOSITORY_ENV) or None,
            webhook_secret=os.environ.get(GITHUB_WEBHOOK_SECRET_ENV) or None,
            expected_installation_id=os.environ.get(GITHUB_EXPECTED_INSTALLATION_ENV) or None,
            transport=os.environ.get(GITHUB_TRANSPORT_ENV) or "development-token",
            api_base_url=os.environ.get("AGENT_BOUNTY_GITHUB_API_BASE_URL", "https://api.github.com"),
        )

    def blockers(self) -> list[str]:
        blockers: list[str] = []
        if not self.enabled:
            blockers.append(f"set {GITHUB_INTEGRATION_ENV}=1")
        if not self.token:
            blockers.append(f"set {GITHUB_TOKEN_ENV} or GH_TOKEN to a fine-grained development token")
        if not self.repository:
            blockers.append(f"set {GITHUB_REPOSITORY_ENV}=owner/repo")
        if not self.webhook_secret:
            blockers.append(f"set {GITHUB_WEBHOOK_SECRET_ENV} for signed webhook ingestion")
        return blockers


class GitHubRestClient:
    def __init__(self, config: GitHubConfig):
        if not config.token:
            raise GitHubIntegrationError(f"set {GITHUB_TOKEN_ENV} or GH_TOKEN")
        self.config = config

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else stable_json(body).encode("utf-8")
        req = urllib.request.Request(
            self.config.api_base_url.rstrip("/") + path,
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "User-Agent": "agent-bounty-market/0.1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")[:400]
            raise GitHubIntegrationError(f"GitHub API {method} {path} failed: HTTP {exc.code}: {raw}") from exc
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise GitHubIntegrationError("GitHub API returned a non-object response")
        return value

    def current_user(self) -> dict[str, Any]:
        return self._request("GET", "/user")

    def get_repo(self, repo_full_name: str) -> dict[str, Any]:
        return self._request("GET", f"/repos/{repo_full_name}")

    def create_issue(self, repo_full_name: str, *, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return self._request("POST", f"/repos/{repo_full_name}/issues", payload)

    def update_issue(self, repo_full_name: str, issue_number: int, *, title: str | None = None, body: str | None = None, state: str | None = None) -> dict[str, Any]:
        payload = {key: value for key, value in {"title": title, "body": body, "state": state}.items() if value is not None}
        return self._request("PATCH", f"/repos/{repo_full_name}/issues/{issue_number}", payload)

    def get_issue(self, repo_full_name: str, issue_number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{repo_full_name}/issues/{issue_number}")

    def add_issue_comment(self, repo_full_name: str, issue_number: int, body: str) -> dict[str, Any]:
        return self._request("POST", f"/repos/{repo_full_name}/issues/{issue_number}/comments", {"body": body})

    def get_pull_request(self, repo_full_name: str, pr_number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{repo_full_name}/pulls/{pr_number}")

    def create_pull_request(self, repo_full_name: str, *, title: str, body: str, head: str, base: str, draft: bool = True) -> dict[str, Any]:
        return self._request("POST", f"/repos/{repo_full_name}/pulls", {"title": title, "body": body, "head": head, "base": base, "draft": draft})

    def create_commit_status(self, repo_full_name: str, sha: str, *, state: str, context: str, description: str, target_url: str | None = None) -> dict[str, Any]:
        payload = {"state": state, "context": context, "description": description}
        if target_url:
            payload["target_url"] = target_url
        return self._request("POST", f"/repos/{repo_full_name}/statuses/{sha}", payload)


class FakeGitHubClient:
    def __init__(self, *, login: str = "agent-bounty-bot"):
        self.login = login
        self.issues: dict[tuple[str, int], dict[str, Any]] = {}
        self.comments: list[dict[str, Any]] = []
        self.pull_requests: dict[tuple[str, int], dict[str, Any]] = {}
        self.statuses: list[dict[str, Any]] = []
        self.next_issue_number = 1
        self.next_comment_id = 1

    def current_user(self) -> dict[str, Any]:
        return {"login": self.login, "id": 1}

    def get_repo(self, repo_full_name: str) -> dict[str, Any]:
        return {"id": abs(hash(repo_full_name)) % 1_000_000, "full_name": repo_full_name, "default_branch": "main"}

    def create_issue(self, repo_full_name: str, *, title: str, body: str, labels: list[str] | None = None) -> dict[str, Any]:
        number = self.next_issue_number
        self.next_issue_number += 1
        issue = {
            "id": number,
            "number": number,
            "title": title,
            "body": body,
            "html_url": f"https://github.test/{repo_full_name}/issues/{number}",
            "labels": labels or [],
            "state": "open",
            "updated_at": utc_now(),
        }
        self.issues[(repo_full_name, number)] = issue
        return dict(issue)

    def update_issue(self, repo_full_name: str, issue_number: int, *, title: str | None = None, body: str | None = None, state: str | None = None) -> dict[str, Any]:
        issue = self.issues[(repo_full_name, int(issue_number))]
        if title is not None:
            issue["title"] = title
        if body is not None:
            issue["body"] = body
        if state is not None:
            issue["state"] = state
        issue["updated_at"] = utc_now()
        return dict(issue)

    def get_issue(self, repo_full_name: str, issue_number: int) -> dict[str, Any]:
        return dict(self.issues[(repo_full_name, int(issue_number))])

    def add_issue_comment(self, repo_full_name: str, issue_number: int, body: str) -> dict[str, Any]:
        comment = {
            "id": self.next_comment_id,
            "body": body,
            "html_url": f"https://github.test/{repo_full_name}/issues/{issue_number}#issuecomment-{self.next_comment_id}",
            "user": {"login": self.login},
        }
        self.next_comment_id += 1
        self.comments.append({"repo_full_name": repo_full_name, "issue_number": int(issue_number), **comment})
        return dict(comment)

    def create_fake_pull_request(
        self,
        repo_full_name: str,
        *,
        number: int,
        title: str,
        body: str,
        base_ref: str,
        base_sha: str,
        head_ref: str,
        head_sha: str,
        head_repo_full_name: str | None = None,
        user_login: str = "solver",
        draft: bool = True,
    ) -> dict[str, Any]:
        pr = {
            "id": number,
            "number": int(number),
            "title": title,
            "body": body,
            "html_url": f"https://github.test/{repo_full_name}/pull/{number}",
            "state": "open",
            "draft": draft,
            "user": {"login": user_login},
            "base": {"ref": base_ref, "sha": base_sha, "repo": {"full_name": repo_full_name}},
            "head": {"ref": head_ref, "sha": head_sha, "repo": {"full_name": head_repo_full_name or repo_full_name}},
        }
        self.pull_requests[(repo_full_name, int(number))] = pr
        return dict(pr)

    def get_pull_request(self, repo_full_name: str, pr_number: int) -> dict[str, Any]:
        return dict(self.pull_requests[(repo_full_name, int(pr_number))])

    def create_pull_request(self, repo_full_name: str, *, title: str, body: str, head: str, base: str, draft: bool = True) -> dict[str, Any]:
        number = max([key[1] for key in self.pull_requests if key[0] == repo_full_name] or [0]) + 1
        marker = parse_submission_marker(body)
        return self.create_fake_pull_request(
            repo_full_name,
            number=number,
            title=title,
            body=body,
            base_ref=base,
            base_sha=str(marker.get("base_commit") if marker else "base"),
            head_ref=head,
            head_sha=str(marker.get("candidate_commit") if marker else "candidate"),
            draft=draft,
        )

    def create_commit_status(self, repo_full_name: str, sha: str, *, state: str, context: str, description: str, target_url: str | None = None) -> dict[str, Any]:
        status = {
            "id": len(self.statuses) + 1,
            "state": state,
            "context": context,
            "description": description,
            "target_url": target_url,
            "sha": sha,
            "repository": repo_full_name,
            "html_url": f"https://github.test/{repo_full_name}/commit/{sha}/status/{len(self.statuses) + 1}",
        }
        self.statuses.append(status)
        return dict(status)


def gh_cli_version() -> str | None:
    executable = shutil.which("gh")
    if not executable:
        return None
    try:
        return subprocess.run([executable, "--version"], check=False, capture_output=True, text=True, timeout=5).stdout.splitlines()[0]
    except Exception:
        return None


def contract_digest(contract: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in contract.items() if key != "contract_digest"}
    return sha256_text(stable_json(unsigned))


def build_contract_payload(
    *,
    project_id: str,
    bounty_id: str,
    repository: str,
    issue_number: int | None,
    client_request_id: str,
    base_commit: str,
    reward_amount: int,
    currency: str,
    funding_id: str | None,
    reservation_id: str | None,
    verifier_id: str,
    verifier_version: str,
    verifier_digest: str,
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    required_checks: list[str] | None = None,
    claim_lease_seconds: int = 86_400,
    submission_deadline: str | None = None,
    human_approval_policy: str = "required-above-policy-threshold",
    created_at: str | None = None,
) -> dict[str, Any]:
    body = {
        "schema": CONTRACT_SCHEMA,
        "project_id": project_id,
        "bounty_id": bounty_id,
        "repository": repository,
        "issue_number": issue_number,
        "client_request_id": client_request_id,
        "base_commit": base_commit,
        "reward": {"amount": int(reward_amount), "currency": currency.upper()},
        "funding_id": funding_id,
        "reservation_id": reservation_id,
        "verifier": {"id": verifier_id, "version": verifier_version, "digest": verifier_digest},
        "allowed_paths": allowed_paths or [],
        "forbidden_paths": forbidden_paths or [],
        "required_checks": required_checks or [],
        "claim_lease_seconds": int(claim_lease_seconds),
        "submission_deadline": submission_deadline,
        "human_approval_policy": human_approval_policy,
        "created_at": created_at or utc_now(),
    }
    body["contract_digest"] = contract_digest(body)
    return body


def render_contract_issue_body(human_body: str, contract: dict[str, Any]) -> str:
    return human_body.rstrip() + "\n\n<!-- agent-bounty-contract-v1 " + stable_json(contract) + " -->\n"


def render_contract_issue_body_preserving(existing_body: str, contract: dict[str, Any]) -> str:
    body = CONTRACT_RE.sub("", existing_body or "").rstrip()
    return render_contract_issue_body(body, contract)


def parse_contract_from_issue_body(body: str, *, expected_digest: str | None = None) -> dict[str, Any]:
    matches = CONTRACT_RE.findall(body or "")
    if len(matches) != 1:
        raise GitHubIntegrationError(f"expected exactly one {CONTRACT_SCHEMA} block; found {len(matches)}")
    try:
        contract = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise GitHubIntegrationError("GitHub bounty contract JSON is malformed") from exc
    if not isinstance(contract, dict) or contract.get("schema") != CONTRACT_SCHEMA:
        raise GitHubIntegrationError("GitHub bounty contract schema mismatch")
    declared = contract.get("contract_digest")
    if not isinstance(declared, str) or not declared.startswith("sha256:"):
        raise GitHubIntegrationError("GitHub bounty contract is missing contract_digest")
    actual = contract_digest(contract)
    if not hmac.compare_digest(declared, actual):
        raise GitHubIntegrationError("GitHub bounty contract digest mismatch")
    if expected_digest and not hmac.compare_digest(expected_digest, declared):
        raise GitHubIntegrationError("GitHub bounty contract does not match expected digest")
    return contract


def build_claim_comment(*, bounty_id: str, solver_id: str, lease_expires_at: str, contract_digest_value: str) -> str:
    payload = {
        "schema": CLAIM_SCHEMA,
        "bounty_id": bounty_id,
        "solver_id": solver_id,
        "lease_expires_at": lease_expires_at,
        "contract_digest": contract_digest_value,
    }
    payload["claim_digest"] = sha256_text(stable_json(payload))
    return "<!-- agent-bounty-claim-v1 " + stable_json(payload) + " -->"


def parse_claim_comment(body: str) -> dict[str, Any] | None:
    matches = CLAIM_RE.findall(body or "")
    if not matches:
        return None
    if len(matches) != 1:
        raise GitHubIntegrationError("ambiguous GitHub claim comment")
    payload = json.loads(matches[0])
    if payload.get("schema") != CLAIM_SCHEMA:
        raise GitHubIntegrationError("GitHub claim schema mismatch")
    declared = payload.get("claim_digest")
    unsigned = {key: value for key, value in payload.items() if key != "claim_digest"}
    if not isinstance(declared, str) or not hmac.compare_digest(declared, sha256_text(stable_json(unsigned))):
        raise GitHubIntegrationError("GitHub claim digest mismatch")
    return payload


def build_submission_marker(*, bounty_id: str, solver_id: str, contract_digest_value: str, issue_number: int, base_commit: str, candidate_commit: str) -> str:
    payload = {
        "schema": SUBMISSION_SCHEMA,
        "bounty_id": bounty_id,
        "solver_id": solver_id,
        "contract_digest": contract_digest_value,
        "issue_number": int(issue_number),
        "base_commit": base_commit,
        "candidate_commit": candidate_commit,
    }
    payload["submission_digest"] = sha256_text(stable_json(payload))
    return "<!-- agent-bounty-submission-v1 " + stable_json(payload) + " -->"


def parse_submission_marker(body: str) -> dict[str, Any] | None:
    matches = SUBMISSION_RE.findall(body or "")
    if not matches:
        return None
    if len(matches) != 1:
        raise GitHubIntegrationError("ambiguous GitHub submission marker")
    payload = json.loads(matches[0])
    if payload.get("schema") != SUBMISSION_SCHEMA:
        raise GitHubIntegrationError("GitHub submission schema mismatch")
    declared = payload.get("submission_digest")
    unsigned = {key: value for key, value in payload.items() if key != "submission_digest"}
    if not isinstance(declared, str) or not hmac.compare_digest(declared, sha256_text(stable_json(unsigned))):
        raise GitHubIntegrationError("GitHub submission digest mismatch")
    return payload


def sign_github_payload(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, "sha256").hexdigest()
    return f"sha256={digest}"


def verify_github_signature(*, payload: bytes, signature_header: str, endpoint_secret: str) -> None:
    if not endpoint_secret:
        raise GitHubIntegrationError("GitHub webhook secret is required")
    if not signature_header.startswith("sha256="):
        raise GitHubIntegrationError("GitHub webhook signature header is missing sha256")
    expected = sign_github_payload(payload, endpoint_secret)
    if not hmac.compare_digest(signature_header, expected):
        raise GitHubIntegrationError("GitHub webhook signature verification failed")


def normalize_headers(headers: dict[str, str] | Any) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in dict(headers).items()}


def _safe_user(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {"login": value.get("login"), "id": value.get("id")}


def _safe_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    repo = value.get("repo") if isinstance(value.get("repo"), dict) else {}
    return {"ref": value.get("ref"), "sha": value.get("sha"), "repo": {"full_name": repo.get("full_name"), "id": repo.get("id")}}


def _safe_pr(pr: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pr.get("id"),
        "number": pr.get("number"),
        "body": pr.get("body"),
        "html_url": pr.get("html_url"),
        "state": pr.get("state"),
        "draft": bool(pr.get("draft", False)),
        "user": _safe_user(pr.get("user")),
        "base": _safe_ref(pr.get("base")),
        "head": _safe_ref(pr.get("head")),
    }


def safe_github_payload(event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    repository = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    safe: dict[str, Any] = {
        "action": payload.get("action"),
        "repository": {"full_name": repository.get("full_name"), "id": repository.get("id")},
    }
    if isinstance(payload.get("installation"), dict):
        safe["installation"] = {"id": payload["installation"].get("id")}
    if event_name == "issues" and isinstance(payload.get("issue"), dict):
        issue = payload["issue"]
        safe["issue"] = {"id": issue.get("id"), "number": issue.get("number"), "body": issue.get("body"), "html_url": issue.get("html_url")}
    if event_name == "issue_comment" and isinstance(payload.get("issue"), dict):
        issue = payload["issue"]
        comment = payload.get("comment") if isinstance(payload.get("comment"), dict) else {}
        safe["issue"] = {"id": issue.get("id"), "number": issue.get("number"), "body": issue.get("body"), "html_url": issue.get("html_url")}
        safe["comment"] = {"id": comment.get("id"), "body": comment.get("body"), "user": _safe_user(comment.get("user"))}
    if event_name == "pull_request" and isinstance(payload.get("pull_request"), dict):
        safe["pull_request"] = _safe_pr(payload["pull_request"])
    for key in ("check_run", "check_suite", "workflow_run"):
        if isinstance(payload.get(key), dict):
            item = payload[key]
            safe[key] = {"id": item.get("id"), "head_sha": item.get("head_sha"), "status": item.get("status"), "conclusion": item.get("conclusion")}
    if event_name == "status":
        safe["status"] = {"id": payload.get("id"), "sha": payload.get("sha"), "state": payload.get("state"), "context": payload.get("context")}
    return safe


def _event_object_id(event_name: str, payload: dict[str, Any]) -> str | None:
    if event_name in {"issues", "issue_comment"}:
        issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
        return str(issue.get("number")) if issue.get("number") is not None else None
    if event_name == "pull_request":
        pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
        return str(pr.get("number")) if pr.get("number") is not None else None
    for key in ("check_run", "check_suite", "workflow_run", "status"):
        obj = payload.get(key) if isinstance(payload.get(key), dict) else None
        if obj and obj.get("id") is not None:
            return str(obj.get("id"))
    return None


def record_github_webhook_delivery(
    conn: Any,
    *,
    payload: bytes,
    headers: dict[str, str] | Any,
    endpoint_secret: str,
    expected_repo_full_name: str | None = None,
    allowed_events: set[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_headers(headers)
    delivery_id = normalized.get("x-github-delivery")
    event_name = normalized.get("x-github-event")
    signature = normalized.get("x-hub-signature-256", "")
    if not delivery_id:
        raise GitHubIntegrationError("GitHub webhook missing X-GitHub-Delivery")
    if not event_name:
        raise GitHubIntegrationError("GitHub webhook missing X-GitHub-Event")
    if event_name not in (allowed_events or ALLOWED_GITHUB_EVENTS):
        raise GitHubIntegrationError(f"GitHub webhook event {event_name} is not allowed")
    verify_github_signature(payload=payload, signature_header=signature, endpoint_secret=endpoint_secret)
    payload_sha = sha256_bytes(payload)
    existing = conn.execute("SELECT * FROM github_webhook_deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
    if existing:
        if existing["payload_sha256"] != payload_sha:
            raise GitHubIntegrationError("GitHub delivery id replayed with different payload")
        return {"delivery_id": delivery_id, "event_name": existing["event_name"], "replayed": True, "status": existing["status"], "action_result": existing["action_result"]}
    try:
        event = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubIntegrationError("GitHub webhook payload must be UTF-8 JSON") from exc
    if not isinstance(event, dict):
        raise GitHubIntegrationError("GitHub webhook payload must be an object")
    safe_payload = safe_github_payload(event_name, event)
    repo_data = safe_payload.get("repository") if isinstance(safe_payload.get("repository"), dict) else {}
    repo_full_name = repo_data.get("full_name")
    if expected_repo_full_name and repo_full_name != expected_repo_full_name:
        raise GitHubIntegrationError("GitHub webhook repository mismatch")
    installation = safe_payload.get("installation") if isinstance(safe_payload.get("installation"), dict) else {}
    action = safe_payload.get("action") if isinstance(safe_payload.get("action"), str) else None
    object_id = _event_object_id(event_name, safe_payload)
    with conn:
        if repo_full_name:
            now = utc_now()
            conn.execute(
                """
                INSERT INTO github_repositories(id, full_name, installation_id, default_branch, created_at, updated_at)
                VALUES (?, ?, ?, NULL, ?, ?)
                ON CONFLICT(full_name) DO UPDATE SET
                    installation_id = COALESCE(excluded.installation_id, installation_id),
                    updated_at = excluded.updated_at
                """,
                (f"repo_{sha256_text(str(repo_full_name))[-16:]}", repo_full_name, str(installation.get("id")) if installation.get("id") is not None else None, now, now),
            )
        conn.execute(
            """
            INSERT INTO github_webhook_deliveries(
                delivery_id, event_name, action, repo_full_name, object_id, payload_sha256,
                signature_valid, safe_payload_json, received_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 'recorded')
            """,
            (delivery_id, event_name, action, repo_full_name, object_id, payload_sha, stable_json(safe_payload), utc_now()),
        )
    return {"delivery_id": delivery_id, "event_name": event_name, "replayed": False, "status": "recorded", "action_result": None}


def finish_github_delivery(conn: Any, *, delivery_id: str, status: str, action_result: str | None = None, error: str | None = None) -> None:
    conn.execute(
        """
        UPDATE github_webhook_deliveries
        SET status = ?, action_result = COALESCE(?, action_result), error = ?,
            processed_at = ?, processing_attempts = processing_attempts + 1
        WHERE delivery_id = ?
        """,
        (status, action_result, error, utc_now(), delivery_id),
    )


def begin_github_operation(conn: Any, *, kind: str, idempotency_key: str, request_parameters_digest: str) -> tuple[str, bool]:
    existing = conn.execute("SELECT * FROM github_operations WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    if existing:
        if existing["kind"] != kind or existing["request_parameters_digest"] != request_parameters_digest:
            raise GitHubIntegrationError("GitHub operation idempotency key replayed with different parameters")
        return existing["id"], True
    operation_id = "ghop_" + sha256_text(idempotency_key)[-24:]
    now = utc_now()
    conn.execute(
        """
        INSERT INTO github_operations(id, kind, idempotency_key, request_parameters_digest, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
        """,
        (operation_id, kind, idempotency_key, request_parameters_digest, now, now),
    )
    return operation_id, False


def finish_github_operation(
    conn: Any,
    *,
    operation_id: str,
    status: str,
    github_object_type: str | None = None,
    github_object_id: str | None = None,
    github_url: str | None = None,
    safe_error_message: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE github_operations
        SET status = ?, github_object_type = COALESCE(?, github_object_type),
            github_object_id = COALESCE(?, github_object_id), github_url = COALESCE(?, github_url),
            safe_error_message = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, github_object_type, github_object_id, github_url, safe_error_message, utc_now(), operation_id),
    )


def save_issue_contract(conn: Any, *, bounty_id: str, repo_full_name: str, issue_number: int, issue_url: str | None, issue_body: str, contract: dict[str, Any]) -> dict[str, Any]:
    row_id = "ghc_" + sha256_text(f"{repo_full_name}#{issue_number}:{contract['contract_digest']}")[-24:]
    now = utc_now()
    with conn:
        conn.execute(
            """
            INSERT INTO github_issue_contracts(
                id, bounty_id, repo_full_name, issue_number, issue_url, contract_schema,
                contract_digest, issue_body_digest, issue_body_json, contract_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_full_name, issue_number, contract_digest) DO UPDATE SET
                issue_url = excluded.issue_url,
                issue_body_digest = excluded.issue_body_digest,
                issue_body_json = excluded.issue_body_json,
                contract_json = excluded.contract_json,
                updated_at = excluded.updated_at
            """,
            (
                row_id,
                bounty_id,
                repo_full_name,
                int(issue_number),
                issue_url,
                CONTRACT_SCHEMA,
                contract["contract_digest"],
                sha256_text(issue_body),
                stable_json({"body": issue_body}),
                stable_json(contract),
                now,
                now,
            ),
        )
    return {"contract_id": row_id, "contract_digest": contract["contract_digest"], "issue_number": int(issue_number), "repo_full_name": repo_full_name}


def github_publish_bounty_contract(
    market: Any,
    *,
    client: Any,
    repo_full_name: str,
    bounty_id: str,
    human_body: str,
    title: str | None = None,
    issue_number: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    bounty = market.conn.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
    if not bounty:
        raise GitHubIntegrationError(f"unknown bounty {bounty_id}")
    existing_issue = client.get_issue(repo_full_name, int(issue_number)) if issue_number else None
    existing_body = str(existing_issue.get("body") or "") if existing_issue else human_body
    existing_created_at = None
    if issue_number:
        try:
            existing_contract = parse_contract_from_issue_body(existing_body)
            if existing_contract.get("bounty_id") == bounty_id and existing_contract.get("base_commit") == bounty["base_commit"]:
                existing_created_at = existing_contract.get("created_at")
        except GitHubIntegrationError:
            existing_created_at = None
    contract = build_contract_payload(
        project_id=bounty["project_id"],
        bounty_id=bounty_id,
        repository=repo_full_name,
        issue_number=issue_number,
        client_request_id=f"github:{repo_full_name}:{bounty_id}",
        base_commit=bounty["base_commit"],
        reward_amount=int(bounty["reward_amount"]),
        currency=bounty["currency"],
        funding_id=None,
        reservation_id=bounty["reserve_idempotency_key"],
        verifier_id=bounty["verifier_id"],
        verifier_version="2.0.0" if bounty["verifier_id"].endswith("v2") else "1.0.0",
        verifier_digest="sha256:verifier-policy-recorded-in-repo",
        forbidden_paths=["verifiers/", ".github/workflows/"],
        required_checks=["agent-bounty/protected-verifier"],
        submission_deadline="2026-06-30T18:00:00Z",
        created_at=existing_created_at,
    )
    body = render_contract_issue_body_preserving(existing_body, contract) if issue_number else render_contract_issue_body(human_body, contract)
    params = {"repo_full_name": repo_full_name, "issue_number": issue_number, "title": title or bounty["title"], "body_digest": sha256_text(body)}
    key = idempotency_key or f"github-publish-contract:{repo_full_name}:{bounty_id}:{issue_number or 'new'}:{sha256_text(body)[-16:]}"
    with market.conn:
        operation_id, replayed = begin_github_operation(market.conn, kind="issue_contract_publish", idempotency_key=key, request_parameters_digest=request_digest(params))
    if replayed:
        existing = market.conn.execute("SELECT * FROM github_operations WHERE id = ?", (operation_id,)).fetchone()
        row = market.conn.execute("SELECT * FROM github_issue_contracts WHERE bounty_id = ? ORDER BY updated_at DESC LIMIT 1", (bounty_id,)).fetchone()
        return {"operation_id": operation_id, "replayed": True, "issue_url": existing["github_url"], "contract_digest": row["contract_digest"] if row else contract["contract_digest"]}
    try:
        issue = client.update_issue(repo_full_name, issue_number, title=title, body=body) if issue_number else client.create_issue(repo_full_name, title=title or bounty["title"], body=body, labels=["agent-bounty"])
        number = int(issue["number"])
        if contract["issue_number"] != number:
            contract["issue_number"] = number
            contract["contract_digest"] = contract_digest(contract)
            body = render_contract_issue_body_preserving(existing_body, contract) if issue_number else render_contract_issue_body(human_body, contract)
            issue = client.update_issue(repo_full_name, number, body=body)
        saved = save_issue_contract(market.conn, bounty_id=bounty_id, repo_full_name=repo_full_name, issue_number=number, issue_url=issue.get("html_url"), issue_body=body, contract=contract)
        with market.conn:
            finish_github_operation(market.conn, operation_id=operation_id, status="succeeded", github_object_type="issue", github_object_id=str(number), github_url=issue.get("html_url"))
        return {"operation_id": operation_id, "replayed": False, "issue_number": number, "issue_url": issue.get("html_url"), **saved}
    except Exception as exc:
        with market.conn:
            finish_github_operation(market.conn, operation_id=operation_id, status="failed", safe_error_message=safe_error_message(exc))
        raise


def github_import_bounty_contract(market: Any, *, repo_full_name: str, issue_number: int, issue_body: str, issue_url: str | None = None, expected_digest: str | None = None) -> dict[str, Any]:
    contract = parse_contract_from_issue_body(issue_body, expected_digest=expected_digest)
    bounty = market.conn.execute("SELECT * FROM bounties WHERE id = ?", (contract["bounty_id"],)).fetchone()
    if not bounty:
        raise GitHubIntegrationError(f"contract references unknown bounty {contract['bounty_id']}")
    if bounty["project_id"] != contract["project_id"] or bounty["base_commit"] != contract["base_commit"]:
        raise GitHubIntegrationError("contract does not match local bounty")
    return save_issue_contract(market.conn, bounty_id=contract["bounty_id"], repo_full_name=repo_full_name, issue_number=issue_number, issue_url=issue_url, issue_body=issue_body, contract=contract)


def github_publish_claim_comment(
    market: Any,
    *,
    client: Any,
    repo_full_name: str,
    issue_number: int,
    bounty_id: str,
    solver_id: str,
    lease_expires_at: str,
    contract_digest_value: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    contract_row = None
    if contract_digest_value:
        contract_row = contract_row_for_digest(market.conn, contract_digest_value)
    else:
        contract_row = market.conn.execute(
            "SELECT * FROM github_issue_contracts WHERE bounty_id = ? AND repo_full_name = ? AND issue_number = ? ORDER BY updated_at DESC LIMIT 1",
            (bounty_id, repo_full_name, int(issue_number)),
        ).fetchone()
    if not contract_row:
        raise GitHubIntegrationError("cannot publish claim without an imported GitHub bounty contract")
    body = build_claim_comment(
        bounty_id=bounty_id,
        solver_id=solver_id,
        lease_expires_at=lease_expires_at,
        contract_digest_value=contract_row["contract_digest"],
    )
    params = {
        "repo_full_name": repo_full_name,
        "issue_number": int(issue_number),
        "body_digest": sha256_text(body),
        "solver_id": solver_id,
    }
    key = idempotency_key or f"github-claim-comment:{repo_full_name}:{issue_number}:{solver_id}:{contract_row['contract_digest']}"
    with market.conn:
        operation_id, replayed = begin_github_operation(market.conn, kind="claim_comment_publish", idempotency_key=key, request_parameters_digest=request_digest(params))
    if replayed:
        existing = market.conn.execute("SELECT * FROM github_operations WHERE id = ?", (operation_id,)).fetchone()
        return {"operation_id": operation_id, "replayed": True, "comment_url": existing["github_url"], "contract_digest": contract_row["contract_digest"]}
    try:
        comment = client.add_issue_comment(repo_full_name, int(issue_number), body)
        with market.conn:
            finish_github_operation(
                market.conn,
                operation_id=operation_id,
                status="succeeded",
                github_object_type="issue_comment",
                github_object_id=str(comment.get("id")),
                github_url=comment.get("html_url"),
            )
        return {
            "operation_id": operation_id,
            "replayed": False,
            "comment_id": comment.get("id"),
            "comment_url": comment.get("html_url"),
            "contract_digest": contract_row["contract_digest"],
            "body": body,
        }
    except Exception as exc:
        with market.conn:
            finish_github_operation(market.conn, operation_id=operation_id, status="failed", safe_error_message=safe_error_message(exc))
        raise


def github_show_contract(issue_body: str, *, expected_digest: str | None = None) -> dict[str, Any]:
    contract = parse_contract_from_issue_body(issue_body, expected_digest=expected_digest)
    return {"schema": "agent-bounty-github-contract-report-v1", "ok": True, "contract": contract}


def process_github_event_row(market: Any, *, delivery_id: str, candidate_repo_path: str | None = None) -> dict[str, Any]:
    row = market.conn.execute("SELECT * FROM github_webhook_deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
    if not row:
        raise GitHubIntegrationError(f"unknown GitHub delivery {delivery_id}")
    if row["status"] == "processed":
        return {"delivery_id": delivery_id, "event_name": row["event_name"], "replayed": True, "action": row["action_result"]}
    payload = parse_json(row["safe_payload_json"], {})
    try:
        action = apply_github_event(market, row=row, payload=payload, candidate_repo_path=candidate_repo_path)
        with market.conn:
            finish_github_delivery(market.conn, delivery_id=delivery_id, status="processed", action_result=action)
        return {"delivery_id": delivery_id, "event_name": row["event_name"], "replayed": False, "action": action}
    except Exception as exc:
        with market.conn:
            finish_github_delivery(market.conn, delivery_id=delivery_id, status="failed", error=safe_error_message(exc))
        raise


def apply_github_event(market: Any, *, row: Any, payload: dict[str, Any], candidate_repo_path: str | None) -> str:
    event_name = row["event_name"]
    if event_name == "issues":
        issue = payload.get("issue") if isinstance(payload.get("issue"), dict) else {}
        body = issue.get("body") if isinstance(issue.get("body"), str) else ""
        if CONTRACT_SCHEMA in body:
            github_import_bounty_contract(market, repo_full_name=row["repo_full_name"], issue_number=int(issue["number"]), issue_body=body, issue_url=issue.get("html_url"))
            return "issue_contract_imported"
        return "issue_recorded_without_contract"
    if event_name == "issue_comment":
        return apply_issue_comment(market, row=row, payload=payload)
    if event_name == "pull_request":
        return apply_pull_request(market, row=row, payload=payload, candidate_repo_path=candidate_repo_path)
    if event_name in {"check_run", "check_suite", "workflow_run", "status"}:
        return "recorded_non_authoritative_ci_event"
    if event_name in {"installation", "repository"}:
        return "recorded_metadata_event"
    return "ignored_event"


def contract_row_for_digest(conn: Any, digest: str) -> Any:
    row = conn.execute("SELECT * FROM github_issue_contracts WHERE contract_digest = ? ORDER BY updated_at DESC LIMIT 1", (digest,)).fetchone()
    if not row:
        raise GitHubIntegrationError("unknown GitHub contract digest")
    return row


def apply_issue_comment(market: Any, *, row: Any, payload: dict[str, Any]) -> str:
    comment = payload.get("comment") if isinstance(payload.get("comment"), dict) else {}
    claim = parse_claim_comment(comment.get("body") if isinstance(comment.get("body"), str) else "")
    if not claim:
        return "ignored_unstructured_comment"
    contract_row = contract_row_for_digest(market.conn, claim["contract_digest"])
    if contract_row["bounty_id"] != claim["bounty_id"]:
        raise GitHubIntegrationError("claim bounty does not match contract")
    market.create_solver(solver_id=claim["solver_id"], display_name=claim["solver_id"], idempotency_key=f"github-beneficiary:{claim['solver_id']}")
    result = market.claim_bounty(
        bounty_id=claim["bounty_id"],
        solver_id=claim["solver_id"],
        lease_expires_at=claim["lease_expires_at"],
        idempotency_key=f"github-claim:{claim['contract_digest']}:{claim['solver_id']}",
    )
    return "claim_replayed" if result.get("replayed") else "claim_recorded"


def apply_pull_request(market: Any, *, row: Any, payload: dict[str, Any], candidate_repo_path: str | None) -> str:
    pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
    if not pr:
        return "ignored_missing_pr"
    marker = parse_submission_marker(pr.get("body") if isinstance(pr.get("body"), str) else "")
    repo_full_name = row["repo_full_name"]
    pr_number = int(pr["number"])
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    base_repo = (base.get("repo") or {}).get("full_name") if isinstance(base.get("repo"), dict) else None
    head_repo = (head.get("repo") or {}).get("full_name") if isinstance(head.get("repo"), dict) else None
    now = utc_now()
    with market.conn:
        market.conn.execute(
            """
            INSERT INTO github_pull_requests(
                id, repo_full_name, pr_number, issue_number, bounty_id, solver_id,
                base_repo, base_ref, base_sha, head_repo, head_ref, head_sha,
                state, draft, body_digest, verification_eligible, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(repo_full_name, pr_number) DO UPDATE SET
                base_sha = excluded.base_sha,
                head_sha = excluded.head_sha,
                state = excluded.state,
                draft = excluded.draft,
                body_digest = excluded.body_digest,
                verification_eligible = 0,
                updated_at = excluded.updated_at
            """,
            (
                f"ghpr_{sha256_text(f'{repo_full_name}#{pr_number}')[-24:]}",
                repo_full_name,
                pr_number,
                int(marker["issue_number"]) if marker else None,
                marker.get("bounty_id") if marker else None,
                marker.get("solver_id") if marker else None,
                base_repo,
                base.get("ref"),
                base.get("sha"),
                head_repo,
                head.get("ref"),
                head.get("sha"),
                pr.get("state"),
                1 if pr.get("draft") else 0,
                sha256_text(pr.get("body") or ""),
                now,
                now,
            ),
        )
    if not marker:
        return "pull_request_recorded_without_submission"
    contract_row = contract_row_for_digest(market.conn, marker["contract_digest"])
    contract = parse_json(contract_row["contract_json"], {})
    if contract_row["repo_full_name"] != repo_full_name:
        raise GitHubIntegrationError("submission repository does not match contract")
    if int(contract_row["issue_number"]) != int(marker["issue_number"]):
        raise GitHubIntegrationError("submission issue does not match contract")
    if base_repo != repo_full_name or base.get("sha") != contract["base_commit"] or marker["base_commit"] != contract["base_commit"]:
        raise GitHubIntegrationError("submission base repository/SHA mismatch")
    if head.get("sha") != marker["candidate_commit"]:
        raise GitHubIntegrationError("submission head SHA does not match marker")
    bounty = market.conn.execute("SELECT * FROM bounties WHERE id = ?", (marker["bounty_id"],)).fetchone()
    if not bounty:
        raise GitHubIntegrationError("submission references unknown bounty")
    existing = market.conn.execute(
        "SELECT * FROM submissions WHERE bounty_id = ? AND solver_id = ? AND candidate_commit = ?",
        (marker["bounty_id"], marker["solver_id"], marker["candidate_commit"]),
    ).fetchone()
    if existing:
        with market.conn:
            market.conn.execute(
                "UPDATE github_pull_requests SET submission_id = ?, verification_eligible = 1, updated_at = ? WHERE repo_full_name = ? AND pr_number = ?",
                (existing["id"], utc_now(), repo_full_name, pr_number),
            )
        return "submission_replayed"
    if bounty["state"] != BountyState.CLAIMED.value:
        return "pull_request_recorded_reverification_required"
    submission = market.submit_candidate(
        bounty_id=marker["bounty_id"],
        solver_id=marker["solver_id"],
        candidate_repo_path=candidate_repo_path or head_repo or repo_full_name,
        candidate_commit=marker["candidate_commit"],
        idempotency_key=f"github-submission:{repo_full_name}:{pr_number}:{marker['candidate_commit']}",
    )
    with market.conn:
        market.conn.execute(
            "UPDATE github_pull_requests SET submission_id = ?, verification_eligible = 1, updated_at = ? WHERE repo_full_name = ? AND pr_number = ?",
            (submission["submission_id"], utc_now(), repo_full_name, pr_number),
        )
    return "submission_recorded"


def github_publish_verification_result(
    market: Any,
    *,
    client: Any,
    repo_full_name: str,
    bounty_id: str,
    receipt_id: str | None = None,
    pr_number: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    receipt = None
    if receipt_id:
        receipt = market.conn.execute("SELECT * FROM verification_receipts WHERE id = ?", (receipt_id,)).fetchone()
    else:
        receipt = market.conn.execute("SELECT * FROM verification_receipts WHERE bounty_id = ? ORDER BY created_at DESC LIMIT 1", (bounty_id,)).fetchone()
    if not receipt:
        raise GitHubIntegrationError("cannot publish GitHub result without a verification receipt")
    pr = None
    if pr_number is not None:
        pr = market.conn.execute("SELECT * FROM github_pull_requests WHERE repo_full_name = ? AND pr_number = ?", (repo_full_name, int(pr_number))).fetchone()
    else:
        pr = market.conn.execute("SELECT * FROM github_pull_requests WHERE bounty_id = ? ORDER BY updated_at DESC LIMIT 1", (bounty_id,)).fetchone()
    accepted = bool(receipt["accepted"])
    state = "success" if accepted else "failure"
    candidate_sha = receipt["candidate_commit"]
    publication = {
        "schema": RESULT_SCHEMA,
        "bounty_id": bounty_id,
        "receipt_id": receipt["id"],
        "accepted": accepted,
        "candidate_sha": candidate_sha,
        "verifier_id": receipt["verifier_id"],
        "verifier_digest": receipt["verifier_digest"],
        "backend_digest": receipt["backend_digest"],
        "policy_digest": receipt["policy_digest"],
        "settlement_eligible": accepted,
    }
    key = idempotency_key or f"github-result:{repo_full_name}:{receipt['id']}"
    params = {"repo_full_name": repo_full_name, "sha": candidate_sha, "publication": publication}
    with market.conn:
        operation_id, replayed = begin_github_operation(market.conn, kind="verification_result_publish", idempotency_key=key, request_parameters_digest=request_digest(params))
    existing_publication = market.conn.execute("SELECT * FROM github_publications WHERE idempotency_key = ?", (key,)).fetchone()
    if replayed and existing_publication:
        return {"operation_id": operation_id, "publication_id": existing_publication["id"], "replayed": True, "kind": existing_publication["kind"], "url": existing_publication["github_url"]}
    try:
        status = client.create_commit_status(
            repo_full_name,
            candidate_sha,
            state=state,
            context="agent-bounty/protected-verifier",
            description=("accepted; settlement eligible" if accepted else "rejected; not settlement eligible"),
        )
        publication_id = "ghpub_" + sha256_text(key)[-24:]
        with market.conn:
            market.conn.execute(
                """
                INSERT INTO github_publications(
                    id, kind, repo_full_name, issue_number, pr_number, sha, receipt_id,
                    status, github_object_id, github_url, idempotency_key,
                    request_parameters_digest, created_at, updated_at
                ) VALUES (?, 'commit_status', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (
                    publication_id,
                    repo_full_name,
                    pr["issue_number"] if pr else None,
                    pr["pr_number"] if pr else pr_number,
                    candidate_sha,
                    receipt["id"],
                    "published",
                    str(status.get("id")),
                    status.get("html_url"),
                    key,
                    request_digest(params),
                    utc_now(),
                    utc_now(),
                ),
            )
            finish_github_operation(market.conn, operation_id=operation_id, status="succeeded", github_object_type="commit_status", github_object_id=str(status.get("id")), github_url=status.get("html_url"))
        return {"operation_id": operation_id, "publication_id": publication_id, "replayed": False, "kind": "commit_status", "url": status.get("html_url"), "publication": publication}
    except Exception as exc:
        with market.conn:
            finish_github_operation(market.conn, operation_id=operation_id, status="failed", safe_error_message=safe_error_message(exc))
        raise


def github_status_report(config: GitHubConfig | None = None) -> dict[str, Any]:
    config = config or GitHubConfig.from_env()
    blockers = config.blockers()
    user = None
    repo = None
    if config.enabled and config.token:
        try:
            client = GitHubRestClient(config)
            user_data = client.current_user()
            user = {"login": user_data.get("login"), "id": user_data.get("id")}
            if config.repository:
                repo_data = client.get_repo(config.repository)
                repo = {"full_name": repo_data.get("full_name"), "id": repo_data.get("id"), "default_branch": repo_data.get("default_branch")}
        except Exception as exc:
            blockers.append(safe_error_message(exc))
    return {
        "schema": "agent-bounty-github-status-v1",
        "ok": not blockers,
        "enabled": config.enabled,
        "transport": config.transport,
        "development_transport": config.transport != "github-app",
        "authenticated_user": user,
        "repository": repo,
        "repository_configured": bool(config.repository),
        "webhook_secret_configured": bool(config.webhook_secret),
        "expected_installation_id": config.expected_installation_id,
        "gh_cli": gh_cli_version(),
        "required_capabilities": ["issues:write", "pull_requests:read", "statuses:write", "metadata:read"],
        "blockers": blockers,
    }
